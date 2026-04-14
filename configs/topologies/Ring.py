"""Bidirectional ring for Ruby simple or Garnet networks.

Use ``--topology Ring --network garnet`` with default table routing
(``--routing-algorithm 0``). Link weights (1 vs 2) bias shortest-path
routing so ordered vnets get deterministic routes; do not use XY routing
on this topology.
"""

from common import FileSystemConfig
from topologies.BaseTopology import SimpleTopology

from m5.objects import *
from m5.params import *


class Ring(SimpleTopology):
    description = "Ring"

    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        nodes = self.nodes

        num_routers = options.num_cpus
        assert num_routers >= 3, (
            "Ring topology needs at least 3 routers (num_cpus); "
            "for two nodes use Pt2Pt or Crossbar."
        )

        link_latency = options.link_latency
        router_latency = options.router_latency

        # set number of controllers linked to each router
        cntrls_per_router, remainder = divmod(len(nodes), num_routers) 
        
        # create list of routers
        routers = [
            Router(router_id=i, latency=router_latency)
            for i in range(num_routers)
        ]
        network.routers = routers

        link_count = 0
        
        # create list of controller nodes that are evenly distributed across routers
        # and a list of remainer nodes that will be linked later
        network_nodes = []
        remainder_nodes = []
        for node_index in range(len(nodes)):
            if node_index < (len(nodes) - remainder):
                network_nodes.append(nodes[node_index])
            else:
                remainder_nodes.append(nodes[node_index])
                
        # create the links from the controller nodes to the routers
        # TODO: consider assignment, currently doing a high order interleave I think?, maybe better to do low order interleave?
        ext_links = []
        for i, n in enumerate(network_nodes):
            cntrl_level, router_id = divmod(i, num_routers)
            assert cntrl_level < cntrls_per_router
            ext_links.append(
                ExtLink(
                    link_id=link_count,
                    ext_node=n,
                    int_node=routers[router_id],
                    latency=link_latency,
                )
            )
            link_count += 1

        # connect the remainer nodes to router 0
        for i, node in enumerate(remainder_nodes):
            assert node.type == "DMA_Controller"
            assert i < remainder
            ext_links.append(
                ExtLink(
                    link_id=link_count,
                    ext_node=node,
                    int_node=routers[0],
                    latency=link_latency,
                )
            )
            link_count += 1

        network.ext_links = ext_links

        # create the links between the routers in a clockwise direction
        int_links = []
        for i in range(num_routers):
            cw_dst = (i + 1) % num_routers
            int_links.append(
                # Internal Link object with source as the current router and destination as the next router in a clockwise direction
                # modulo operation is used to wrap around the list of routers
                IntLink(
                    link_id=link_count,
                    src_node=routers[i],
                    dst_node=routers[cw_dst],
                    src_outport="CW",
                    dst_inport="CCW",
                    latency=link_latency,
                    weight=1,
                )

            )
            link_count += 1

        # create the links between the routers in a counter-clockwise direction 
        for i in range(num_routers):
            ccw_dst = (i - 1) % num_routers
            int_links.append(
                IntLink(
                    link_id=link_count,
                    src_node=routers[i],
                    dst_node=routers[ccw_dst],
                    src_outport="CCW",
                    dst_inport="CW",
                    latency=link_latency,
                    weight=2,
                )
            )
            link_count += 1

        network.int_links = int_links

    def registerTopology(self, options):
        for i in range(options.num_cpus):
            FileSystemConfig.register_node(
                [i], MemorySize(options.mem_size) // options.num_cpus, i
            )
