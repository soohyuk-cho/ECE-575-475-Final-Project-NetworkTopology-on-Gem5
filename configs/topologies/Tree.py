"""Binary tree (heap-index) topology for Ruby simple or Garnet networks.

Routers are arranged as a complete binary tree: router ``i`` (for ``i > 0``)
connects to parent ``(i - 1) // 2``.

Use ``--topology Tree --network garnet`` with default table routing
(``--routing-algorithm 0``) and ``--mesh-rows 0``. Do not use XY or custom
mesh routing on this topology.
"""

from common import FileSystemConfig
from topologies.BaseTopology import SimpleTopology

from m5.objects import *
from m5.params import *


class Tree(SimpleTopology):
    description = "Tree"

    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        nodes = self.nodes

        num_routers = options.num_cpus
        assert num_routers >= 2, (
            "Tree topology needs at least 2 routers (num_cpus): "
            "one edge between root and child."
        )

        link_latency = options.link_latency
        router_latency = options.router_latency

        cntrls_per_router, remainder = divmod(len(nodes), num_routers)

        routers = [
            Router(router_id=i, latency=router_latency)
            for i in range(num_routers)
        ]
        network.routers = routers

        link_count = 0

        network_nodes = []
        remainder_nodes = []
        for node_index in range(len(nodes)):
            if node_index < (len(nodes) - remainder):
                network_nodes.append(nodes[node_index])
            else:
                remainder_nodes.append(nodes[node_index])

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

        # create router links in a binary tree structure
        int_links = []
        for i in range(1, num_routers):
            p = (i - 1) // 2
            int_links.append(
                IntLink(
                    link_id=link_count,
                    src_node=routers[p],
                    dst_node=routers[i],
                    src_outport=f"to_{i}",
                    dst_inport=f"from_{p}",
                    latency=link_latency,
                    weight=1,
                )
            )
            link_count += 1
            int_links.append(
                IntLink(
                    link_id=link_count,
                    src_node=routers[i],
                    dst_node=routers[p],
                    src_outport=f"to_{p}",
                    dst_inport=f"from_{i}",
                    latency=link_latency,
                    weight=1,
                )
            )
            link_count += 1

        network.int_links = int_links

    def registerTopology(self, options):
        for i in range(options.num_cpus):
            FileSystemConfig.register_node(
                [i], MemorySize(options.mem_size) // options.num_cpus, i
            )
